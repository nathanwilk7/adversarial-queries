SELECT count(*)
FROM aka_title, cast_info, comp_cast_type, company_type, complete_cast, keyword, movie_companies, movie_keyword, movie_link, name, person_info, title
WHERE aka_title.production_year = 1983
  AND comp_cast_type.kind = 'complete+verified'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
