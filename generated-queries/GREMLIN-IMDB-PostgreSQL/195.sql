SELECT count(*)
FROM cast_info, company_type, complete_cast, keyword, movie_companies, movie_info, movie_keyword, role_type, title
WHERE company_type.kind = 'special effects companies'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id;
