SELECT count(*)
FROM cast_info, company_type, movie_companies, movie_keyword, movie_link, role_type, title
WHERE cast_info.nr_order = 1
  AND company_type.kind = 'production companies'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
