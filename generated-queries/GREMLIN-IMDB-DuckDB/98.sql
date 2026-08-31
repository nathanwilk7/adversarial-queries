SELECT count(*)
FROM aka_title, cast_info, company_type, kind_type, movie_companies, movie_keyword, name, title
WHERE aka_title.production_year < 2016
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND title.kind_id = kind_type.id;
