SELECT count(*)
FROM aka_title, cast_info, company_type, movie_companies, movie_info_idx, movie_keyword, name, title
WHERE company_type.kind = 'production companies'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.movie_id = title.id;
